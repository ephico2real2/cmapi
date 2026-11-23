"""Routes of the namespaces plugin."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import Depends, Query, Response
from fastapi.responses import JSONResponse

from cmapi import __version__
from cmapi.core.context import AppContext
from cmapi.core.db.repo import AuditRepo, JobRepo, RequestRepo, fingerprint
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.listquery import ListQuery
from cmapi.core.models import (Api, ChangeRequest, NamespaceCreate, NamespaceList, NamespacePatch, NamespaceView,
                               PlanView)
from cmapi.core.pipeline import folder_etag, metadata_of, namespace_doc, require_if_match
from cmapi.core.rejections import record_warned, refusals
from cmapi.core.render.manifests import folder
from cmapi.core.views import request_view
from cmapi.plugins.namespaces.state import sync_view
from cmapi.routers import (ClusterId, DryRun, NamespaceName, caller, ctx, delete_idempotency_key, idempotency_key, if_match,
                           require)
from pydantic import Field

router = DocumentedRouter("namespaces", prefix="/api/v1/clusters/{cluster_id}", version=__version__,
                          group="Namespaces and metadata",
                          description="The managed namespaces of a cluster: read them, and create, change, delete or extend "
                                      "one. Each write returns a change request and becomes a pull request after approval.")

# The problems of each write, by the step of core/pipeline.py that raises them, so each route lists only what it can answer.
# Every write: the cluster, the caller, the Idempotency-Key, Git and the cluster's watch.
WRITE_PROBLEMS = ["cluster-not-found", "cluster-not-writable", "environment-not-served", "environment-forbidden", "plugin-disabled",
                  "validation-failed", "change-pending", "identity-incomplete", "on-behalf-of-required",
                  "idempotency-key-required", "idempotency-replay", "git-unavailable", "cluster-unreachable"]
# A body with onBehalfOf: create and change (resolve_requester). A metadata refusal, team-dl too, is a policy-violation item.
ON_BEHALF_PROBLEMS = ["unknown-user", "on-behalf-of-not-allowed"]
# Rendering and checking the new files: every write but a delete, which renders no namespace (plan_delete).
RENDER_PROBLEMS = ["policy-violation", "capacity-exceeded", "validator-unavailable", "unknown-serviceaccount"]
# A namespace that exists, changed under If-Match.
CHANGE_PROBLEMS = ["object-not-found", "precondition-required", "precondition-failed"]

# The lookup of one cluster's namespaces (#481, design section 4.4): the portal's type-ahead after the cluster is chosen.
SEARCH_LIMIT, SEARCH_LIMIT_MAX = 10, 50
# 63: the longest name or label value, so a longer q can match nothing.
SearchText = Annotated[str | None, Query(max_length=63, examples=["pay"],
                                         description="Text that the name, the team label or the app label contains. Case does "
                                                     "not matter. Names that start with it come first.")]
Mnemonic = Annotated[str | None, Query(examples=["abc"],
                                       description="Only the namespaces of this mnemonic: the value of the key that starts the "
                                                   "namespace name (`namespacePrefix` of metadata-keys.yaml).")]
SearchLimit = Annotated[int | None, Query(ge=1, le=SEARCH_LIMIT_MAX, examples=[SEARCH_LIMIT],
                                          description=f"The most namespaces to return: {SEARCH_LIMIT} when `q` or `mnemonic` "
                                                      f"is sent without it, at most {SEARCH_LIMIT_MAX}. With none of the "
                                                      "three, every namespace is returned, by name.")]


class ExtendBody(Api):
    days: int | None = Field(default=None, description="Days to extend by, up to the environment's limit", examples=[30])
    until: str | None = Field(default=None, description="A date to extend to", examples=["2026-12-15"])
    justification: str | None = Field(default=None, description="Why", examples=["Another sprint"])


class SetBody(Api):
    until: date = Field(description="The expiry date: after today, and at most the environment's maxExtensionDays away",
                        examples=["2026-12-15"])
    justification: str | None = Field(default=None, description="Why", examples=["A test namespace for one sprint"])


class PermanentBody(Api):
    justification: str | None = Field(default=None, description="Why", examples=["The service went to production use"])


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
            # Kyverno's warnings on this plan, beside cmapi's refusals on the Policies tab (#302).
            record_warned(s, c, plan, row.request_id)
            AuditRepo(s).record(who, f"namespace.{plan.action}", f"{plan.cluster_id}/{plan.namespace}",
                                {"requestId": row.request_id, "status": row.status})
            return request_view(repo, row)
    except Problem as exc:
        # Lost a race to the same key: the winner's commit is visible now, and its request is this caller's answer.
        replay = _replay(c, who, key, body) if exc.status == 409 else None
        if replay:
            return replay
        raise


def _namespace_view(c: AppContext, cluster_id: str, obj: dict[str, Any], holders: dict[str, dict[str, str]], *,
                    live_fresh: bool, git: dict[str, dict[str, str]] | None = None,
                    on_cluster: bool = True) -> dict[str, Any]:
    """NamespaceView of a live namespace (or the placeholder of one that only Git holds: on_cluster False). git: its
    labels and annotations in Git, which only the single-namespace read has; without them the sync state cannot compare
    (unknown)."""
    m = obj["metadata"]
    labels, ann = m.get("labels") or {}, m.get("annotations") or {}
    holder = holders.get(m["name"])
    return {"clusterId": cluster_id, "name": m["name"], "env": labels.get("cmapi.net/env"), "team": labels.get("cmapi.net/team"),
            "tier": labels.get("cmapi.net/tier"), "labels": labels, "annotations": ann,
            "managed": labels.get("cmapi.net/managed") == "true", "expiresAt": ann.get("cmapi.net/expires-at"),
            "etag": None, "openRequest": holder["requestId"] if holder else None,
            "mnemonic": c.cfg.metadata.mnemonic(labels, ann), "git": None,
            "sync": sync_view(c.cfg.metadata, git, {"label": labels, "annotation": ann}, holder, live_fresh, on_cluster)}


def _live_namespace(c: AppContext, cluster_id: str, ns: str) -> tuple[dict[str, Any] | None, bool]:
    """(the namespace from the watch cache, whether that watch is fresh). A cluster that is not connected has no cache:
    (None, False), and the read still answers from Git."""
    try:
        cache = c.registry.cache(cluster_id)
        live = cache.namespace(ns)
    except Problem:
        return None, False
    return live, not cache.kind_stale("Namespace")[0]


def _search_row(view: dict[str, Any]) -> dict[str, Any]:
    """The view with the app label beside it, which q matches as the Quotas list does (match_rank)."""
    return {**view, "app": view["labels"].get("cmapi.net/app")}


def _mnemonic_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    """The namespaces of each mnemonic among the rows, by mnemonic: the facets of the lookup."""
    counts: dict[str, int] = {}
    for row in rows:
        if row["mnemonic"]:
            counts[row["mnemonic"]] = counts.get(row["mnemonic"], 0) + 1
    return dict(sorted(counts.items()))


def _namespace_page(c: AppContext, rows: list[dict[str, Any]], q: str | None, mnemonic: str | None,
                    limit: int | None) -> dict[str, Any]:
    """NamespaceList (#481, design section 4.4). With none of q, mnemonic and limit sent: every row by name, as before.
    With any sent, even empty: the first `limit` matches, best first (Lister.ranked, the Quotas list's matching). The
    mnemonic counts are over every filter but the mnemonic, so each chip keeps its number when one is chosen."""
    searching = q is not None or mnemonic is not None or limit is not None
    matched = c.lister.ranked(rows, ListQuery(q=q or ""))
    counts = _mnemonic_counts(matched)
    if mnemonic is not None:
        # Compared as a value: a namespace without a mnemonic never matches one (not even the text "None").
        matched = [row for row in matched if row["mnemonic"] == mnemonic]
    shown = matched[:limit or SEARCH_LIMIT] if searching else matched
    items = [{k: v for k, v in row.items() if k != "app"} for row in shown]
    return {"items": items, "total": len(matched), "facets": {"mnemonics": counts}}


@router.read("/namespaces", summary="List managed namespaces on a cluster",
             returns="The managed namespaces of the cluster that match the filters, with their count and the facets.",
             permission="objects:read", response_model=NamespaceList,
             problems=["cluster-not-found", "cluster-unreachable", "environment-forbidden"])
def list_namespaces(cluster_id: ClusterId, q: SearchText = None, mnemonic: Mnemonic = None, limit: SearchLimit = None,
                    who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """Every namespace labelled cmapi.net/managed=true on the cluster, from the watch cache, with the request
    holding each one's lock. The etag is only on the single-namespace read, because it comes from Git.

    The lookup after a cluster is chosen (#481): `q` matches the name, the team label and the app label, names that
    start with it first, then names that contain it, then team and app matches; `mnemonic` keeps one mnemonic's
    namespaces; `limit` caps the answer. `total` counts every match before the cap, and `facets.mnemonics` the
    namespaces of each mnemonic. Each item's `sync` is `pending` when a request holds it and `unknown` otherwise: the
    list reads no Git, so it compares nothing. With none of the three parameters the list is every namespace by name."""
    st = c.registry.get(cluster_id)
    if st.policy:
        c.cfg.roles.require(who, "objects:read", st.policy.environment)
    cache = c.registry.cache(cluster_id)
    live_fresh = not cache.kind_stale("Namespace")[0]
    with c.db.session() as s:
        holders = RequestRepo(s).open_holders(cluster_id)
    rows = [_search_row(_namespace_view(c, cluster_id, o, holders, live_fresh=live_fresh)) for o in cache.all("Namespace")
            if (o["metadata"].get("labels") or {}).get("cmapi.net/managed") == "true"]
    return _namespace_page(c, rows, q, mnemonic, limit)


# The ETag that get_namespace sets, declared so a client generated from the document can read it (#565). It is opaque
# (RFC 9110, 8.8.3.1), so the description says how to use it, not what it is made of; the example has the real form.
NAMESPACE_ETAG_HEADER = {"ETag": {
    "description": "The namespace's entity tag, quoted: the `etag` of the body. Send it unchanged as `If-Match` on a change "
                   "or a delete. It changes when the `.yaml` files directly in the namespace's folder in Git change.",
    "schema": {"type": "string", "examples": ['"3f9a1c0b7e2d4a68"']}}}


@router.read("/namespaces/{ns}", summary="Get a namespace and its ETag",
             returns="The namespace's labels, annotations, tier and sync state as Git and the cluster hold them, with "
                     "the ETag that a change sends in If-Match.",
             permission="objects:read", response_model=NamespaceView,
             problems=["cluster-not-found", "object-not-found", "git-unavailable", "environment-forbidden"],
             responses={"200": {"headers": NAMESPACE_ETAG_HEADER}})
def get_namespace(cluster_id: ClusterId, ns: NamespaceName, response: Response, who: Identity = Depends(require("objects:read")),
                  c: AppContext = Depends(ctx)) -> dict:
    """The live namespace and the etag of its folder in Git. Send the etag as If-Match on PATCH or DELETE (the `ETag`
    header has the same value).

    `labels` and `annotations` are the live ones, from the watch cache. `git` is the folder's labels and annotations, the
    desired state, from the same read as the etag. Its `edits` give `x-cmapi-edit` of each key of Git that
    metadata-keys.yaml does not declare, so a form can lock it or offer its removal: `mode`, the `reason` to show,
    `sensitive`, and `removable` for a key that no rule admits, which a change may remove and never set (#484). An
    operator-only key's reason names this cluster's environment (#532). The other keys' `x-cmapi-edit` are in
    `GET /api/v1/metadata-keys`. `sync` compares Git with the live namespace (#481): `pending` while a request holds it,
    `drift` when a governed, extra or operator-only key differs (each in `driftedKeys`), `in-sync` when none does, and
    `unknown` when the cluster's watch is not fresh."""
    st = c.registry.get(cluster_id)
    if st.policy:
        c.cfg.roles.require(who, "objects:read", st.policy.environment)
    files, _ = c.pipeline._read_folder(cluster_id, ns)
    live, live_fresh = _live_namespace(c, cluster_id, ns)
    if not files and live is None:
        raise Problem(404, "object-not-found", f"{ns} is not on {cluster_id} and not in Git")
    with c.db.session() as s:
        holders = RequestRepo(s).open_holders(cluster_id)
    obj = live or {"metadata": {"name": ns, "labels": {}, "annotations": {}}}
    git_doc = namespace_doc(files)
    git = metadata_of(git_doc)
    view = _namespace_view(c, cluster_id, obj, holders, live_fresh=live_fresh, git=git if git_doc is not None else None,
                           on_cluster=live is not None)
    environment = st.policy.environment if st.policy else None
    view["git"] = {"labels": git["label"], "annotations": git["annotation"],
                   "edits": c.cfg.metadata.undeclared_edits(git, environment)} \
        if git_doc else None
    view["etag"] = folder_etag(files)
    # Protection from the labels in Git, the input of a delete (plan_delete), not from the live object (#366).
    view["protectedBy"] = c.cfg.approvals.protected_by(git["label"])
    view["protected"] = bool(view["protectedBy"])
    response.headers["ETag"] = f'"{view["etag"]}"'
    return view


@router.write("/namespaces", summary="Create a namespace", permission="namespaces:create", response_model=ChangeRequest,
              dry_run_model=PlanView,
              problems=WRITE_PROBLEMS + ON_BEHALF_PROBLEMS + RENDER_PROBLEMS
              + ["reserved-namespace", "invalid-namespace-name", "namespace-exists", "namespace-exists-unmanaged",
                 "expiration-not-allowed", "expiration-in-past"])
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
    with refusals(c, who, cluster_id, raw.get("namespace") or "", "create", dry_run=dry_run):
        plan = c.pipeline.plan_namespace(who, cluster_id, raw, action="create")
    if dry_run:
        return JSONResponse(PlanView.model_validate(plan.view()).model_dump(by_alias=True), status_code=200)
    return _submit(c, who, plan, key, raw, body.justification)


@router.write("/namespaces/{ns}", summary="Change a namespace", permission="namespaces:write", method="PATCH",
              response_model=ChangeRequest, dry_run_model=PlanView,
              problems=WRITE_PROBLEMS + ON_BEHALF_PROBLEMS + RENDER_PROBLEMS + CHANGE_PROBLEMS + ["no-change"])
def update_namespace(cluster_id: ClusterId, ns: NamespaceName, body: NamespacePatch,
                     dry_run: DryRun = False,
                     key: str | None = Depends(idempotency_key), etag: str | None = Depends(if_match),
                     who: Identity = Depends(require("namespaces:write")), c: AppContext = Depends(ctx)):
    """Changes a namespace that exists: its tier, its custom quota and limits, and its labels and annotations.

    **Merge patch.** `labels` and `annotations` follow JSON Merge Patch (RFC 7396, https://www.rfc-editor.org/rfc/rfc7396):
    a key that the body leaves out keeps its value, a string sets it, and `null` removes it. `x-cmapi-edit` of each key,
    in `GET /api/v1/metadata-keys` and, for the keys that file does not declare, in `git.edits` of the namespace's read,
    says how it may change: `fixed` (the value in Git stays; the same value sent back is accepted), `automatic` (filled at creation;
    a change keeps Git's value, and adoption must supply a missing value), `required` (it changes and is never removed)
    or `optional`. A key that no rule admits can be removed,
    never set. A `sensitive` key adds one approval to the request.

    **Check, then submit.** With `dryRun=true` the answer is 200 with the plan, and nothing is written. `metadataDiff`
    lists each effective change by key as `before`, `after` and `source`: `before` is `null` when the key is added, `after`
    is `null` when it is removed. The same body without `dryRun`, with an Idempotency-Key, opens the request (202).

    **If-Match.** Send the ETag of `GET .../namespaces/{ns}` as If-Match (RFC 9110, section 13.1.1). For a new plan,
    a namespace missing from Git is 404 `object-not-found` before the precondition checks. For an existing namespace,
    missing If-Match is 428 `precondition-required` (RFC 6585, section 3), and so is `*`: it proves no read, so cmapi
    refuses it on purpose, where RFC 9110 lets it match any namespace that exists. A list of tags, sent in one If-Match
    field, passes when one of them is the current etag, by the strong comparison, so a weak tag (`W/"..."`) never matches.
    Otherwise the answer is 412 `precondition-failed` (RFC 9110, section 15.5.13) with the current `etag`: read the
    namespace again, apply the change to it and send it.
    An Idempotency-Key replay still requires If-Match, but does not compare it again: it returns the
    original request in its current state even after Git moves, and `*` is 428 there too. The Idempotency-Key parameter
    says when a retry is a replay. A non-dry-run submission also requires Idempotency-Key (400 without it).
    One request at a time holds a namespace: while another is open, 409 `change-pending` names it in `requestId`.

    **Refusals.** 422 `policy-violation` has one `errors` entry for each key that breaks a rule (`reserved_key`,
    `invalid_key`, `invalid_value`, `derived_key`, `missing_required_key`, `too_many_keys`, `annotations_too_large`).
    A key that only an operator may change is 403 `forbidden` without `namespaces:protect` in the namespace's
    environment. A body that changes nothing is 422 `no-change`."""
    raw = {**body.model_dump(by_alias=True, exclude_none=True), "namespace": ns, "clusterId": cluster_id}
    # exclude_none also drops None inside dicts, and in a merge patch null is what removes a key
    for field in ("labels", "annotations"):
        if getattr(body, field) is not None:
            raw[field] = getattr(body, field)
    key = _idem(key, dry_run)
    replay = _replay(c, who, key, raw)
    if replay:
        require_if_match(etag, "change")              # a replay needs If-Match too, as the first request did (#495)
        return replay
    with refusals(c, who, cluster_id, ns, "update", dry_run=dry_run):
        plan = c.pipeline.plan_namespace(who, cluster_id, raw, action="update", if_match=etag)
    if dry_run:
        return JSONResponse(PlanView.model_validate(plan.view()).model_dump(by_alias=True), status_code=200)
    return _submit(c, who, plan, key, raw, body.justification)


@router.write("/namespaces/{ns}", summary="Delete a namespace", permission="namespaces:write", method="DELETE",
              response_model=ChangeRequest,
              problems=WRITE_PROBLEMS + CHANGE_PROBLEMS + ["namespace-protected"])
def delete_namespace(cluster_id: ClusterId, ns: NamespaceName, key: str | None = Depends(delete_idempotency_key),
                     etag: str | None = Depends(if_match),
                     who: Identity = Depends(require("namespaces:write")), c: AppContext = Depends(ctx)):
    """Opens a delete request: the folder leaves Git after approval, and the namespace waits in awaiting_prune
    until an operator confirms the prune. Needs If-Match, read as on a change: a list of tags passes when one of them is
    the current etag, and `*` is 428 `precondition-required`."""
    raw = {"namespace": ns, "action": "delete", "clusterId": cluster_id}
    key = _idem(key, False)
    replay = _replay(c, who, key, raw)
    if replay:
        require_if_match(etag, "delete")              # a replay needs If-Match too (#495)
        return replay
    with refusals(c, who, cluster_id, ns, "delete", dry_run=False):
        plan = c.pipeline.plan_delete(who, cluster_id, ns, if_match=etag)
    return _submit(c, who, plan, key, raw, None)


# The expiry writes send no onBehalfOf and always change the date, so they have no on-behalf or no-change refusal.
EXPIRY_PROBLEMS = WRITE_PROBLEMS + RENDER_PROBLEMS + CHANGE_PROBLEMS + ["expiration-not-allowed"]


def _expiry_write(c: AppContext, who: Identity, cluster_id: str, raw: dict[str, Any], *, key: str | None, etag: str | None,
                  dry_run: bool, reason: str, justification: str | None, fingerprinted: dict[str, Any] | None = None):
    """The one path of :extend, :set and :makePermanent: a namespace update planned from the date in Git, under If-Match.

    `fingerprinted` is the body that the Idempotency-Key is bound to, when it must differ from what the plan reads: the route
    is part of :set's fingerprint, so the same key sent to another route is another request, not a replay."""
    body = fingerprinted or raw
    key = _idem(key, dry_run)
    replay = _replay(c, who, key, body)
    if replay:
        require_if_match(etag, "change")              # a replay needs If-Match too (#495)
        return replay
    with refusals(c, who, cluster_id, raw["namespace"], reason, dry_run=dry_run):
        plan = c.pipeline.plan_namespace(who, cluster_id, raw, action="update", if_match=etag, reason=reason)
    if dry_run:
        return JSONResponse(PlanView.model_validate(plan.view()).model_dump(by_alias=True), status_code=200)
    return _submit(c, who, plan, key, body, justification)


@router.write("/namespaces/{ns}/expiration:extend", summary="Extend a namespace's expiry", permission="namespaces:write",
              response_model=ChangeRequest, dry_run_model=PlanView,
              problems=EXPIRY_PROBLEMS + ["expiration-not-set", "expiration-in-past", "expiration-limit"])
def extend(cluster_id: ClusterId, ns: NamespaceName, body: ExtendBody, dry_run: DryRun = False, key: str | None = Depends(idempotency_key),
           etag: str | None = Depends(if_match), who: Identity = Depends(require("namespaces:write")),
           c: AppContext = Depends(ctx)):
    """Extends the expiry by `days` (up to the environment's limit) or to `until`. A normal request: plan,
    approval, bot PR. Needs If-Match. `dryRun=true` answers 200 with the plan and the approval that would apply."""
    raw: dict[str, Any] = {"namespace": ns, "clusterId": cluster_id}
    if body.days:
        raw["extendDays"] = body.days
    elif body.until:
        # extendUntil, not expiresAt: the pipeline plans expiresAt as :set, which refuses a namespace that has a date.
        try:
            raw["extendUntil"] = date.fromisoformat(body.until).isoformat()
        except ValueError:
            raise Problem.unprocessable("validation-failed", "until is a date, YYYY-MM-DD") from None
    else:
        raise Problem.unprocessable("validation-failed", "Send days or until")
    return _expiry_write(c, who, cluster_id, raw, key=key, etag=etag, dry_run=dry_run, reason="expiration:extend",
                         justification=body.justification)


@router.write("/namespaces/{ns}/expiration:set", summary="Give a permanent namespace an expiry date", permission="namespaces:write",
              response_model=ChangeRequest, dry_run_model=PlanView,
              problems=EXPIRY_PROBLEMS + ["expiration-already-set", "expiration-in-past", "expiration-limit"])
def set_expiry(cluster_id: ClusterId, ns: NamespaceName, body: SetBody, dry_run: DryRun = False,
               key: str | None = Depends(idempotency_key), etag: str | None = Depends(if_match),
               who: Identity = Depends(require("namespaces:write")), c: AppContext = Depends(ctx)):
    """Gives a namespace that has no expiry the date `until`: after today, and at most the environment's maxExtensionDays
    away. A namespace that has a date is refused with 422 expiration-already-set: use :extend. A normal request: plan,
    approval, bot PR. Needs If-Match. `dryRun=true` answers 200 with the plan and the approval that would apply."""
    raw: dict[str, Any] = {"namespace": ns, "clusterId": cluster_id, "expiresAt": body.until.isoformat()}
    return _expiry_write(c, who, cluster_id, raw, key=key, etag=etag, dry_run=dry_run, reason="expiration:set",
                         justification=body.justification, fingerprinted={**raw, "route": "expiration:set"})


@router.write("/namespaces/{ns}/expiration:makePermanent", summary="Remove a namespace's expiry", permission="namespaces:write",
              response_model=ChangeRequest, dry_run_model=PlanView, problems=EXPIRY_PROBLEMS + ["expiration-not-set"])
def make_permanent(cluster_id: ClusterId, ns: NamespaceName, body: PermanentBody, dry_run: DryRun = False,
                   key: str | None = Depends(idempotency_key), etag: str | None = Depends(if_match),
                   who: Identity = Depends(require("namespaces:write")), c: AppContext = Depends(ctx)):
    """Removes the expiry date (`cmapi.net/expires-at` and `cmapi.net/expiry`), so the namespace no longer expires. It always
    adds an approval from approver-platform (docs/01, Namespace expiration). A namespace with no date is refused with 422
    expiration-not-set. It is taken where expiration is now off too, so a date given while it was on can be removed. A normal request: plan, approval, bot PR. Needs If-Match. `dryRun=true` answers 200 with the plan."""
    raw: dict[str, Any] = {"namespace": ns, "clusterId": cluster_id, "makePermanent": True}
    return _expiry_write(c, who, cluster_id, raw, key=key, etag=etag, dry_run=dry_run, reason="expiration:makePermanent",
                         justification=body.justification)
