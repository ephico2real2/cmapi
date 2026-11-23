"""Caller identity, namespace metadata rules, and cluster import diagnostics, including on-demand credential probes."""
from __future__ import annotations

import functools
import json

from fastapi import Depends, Request, Response

from cmapi.core.context import AppContext
from cmapi.core.docs import CONDITIONAL_READ, CORE, DocumentedRouter, metadata_keys_view
from cmapi.core.errors import Problem
from cmapi.core.etag import etag_matches, etag_of
from cmapi.core.identity.claims import Identity
from cmapi.core.metadata import MetadataKeys
from cmapi.core.models import ClusterList, ClusterView, Me, MetadataKeysView
from cmapi.plugins.expiration.rules import ExpirationRules
from cmapi.routers import ClusterId, caller, ctx, require

router = DocumentedRouter("core", prefix="/api/v1", **CORE)


@router.read("/me", summary="Get the caller's identity and permissions",
             returns="The caller's identity, roles, groups and permissions, with the environments each role covers.",
             permission=None, response_model=Me, problems=["unauthenticated", "idp-unavailable"])
def me(who: Identity = Depends(caller), c: AppContext = Depends(ctx)) -> dict:
    """The caller's identity as cmapi records it, the roles and groups in the token, and the permissions
    each role grants with the environments it covers. The first thing to check when a call returns 403. `operator` says
    whether the caller may set the operator-only keys (namespaces:protect), and `operatorEnvironments` where (#366)."""
    roles = c.cfg.roles
    return {"username": who.username, "kind": who.kind, "client": who.client_id, "roles": sorted(who.roles),
            "groups": sorted(who.groups), "identity": who.record(), "access": roles.describe(who),
            "instance": c.cfg.name, "operator": roles.is_operator(who),
            "operatorEnvironments": roles.operator_environments(who)}


@router.read("/clusters", summary="List known clusters",
             returns="Every cluster with its environment, import status and the findings of its checks.",
             permission="clusters:read", response_model=ClusterList)
def clusters(who: Identity = Depends(require("clusters:read")), c: AppContext = Depends(ctx)) -> dict:
    """Every cluster from clusters.yaml and every imported one, with its import status and the findings
    of the six checks. A cluster with a policy entry but no import Secret shows not-imported."""
    return {"items": [st.view() for st in c.registry.snapshots()]}


@functools.lru_cache(maxsize=4)
def metadata_keys_document(keys: MetadataKeys, expiration: ExpirationRules,
                           environments: tuple[str, ...]) -> tuple[bytes, str]:
    """The body of GET /api/v1/metadata-keys and its strong ETag, built once for each loaded configuration. The files are
    read at start and a change restarts the pods (checksum/config), so a process serves one answer; the cache is keyed by
    the loaded objects, so a test that loads another file gets its own answer. The body holds each environment's
    enabled, allowedAtCreate, maxLifetimeDays, notifyDaysBefore and graceDays of expiration.yaml (#479, D15), so a
    change of one of those alone changes the ETag. maxExtensionDays is not here: GET /api/v1/expirations serves it."""
    body = json.dumps(metadata_keys_view(keys, expiration, environments), separators=(",", ":"),
                      ensure_ascii=False).encode()
    return body, etag_of(body)


@router.read("/metadata-keys", summary="Get namespace label and annotation rules",
             returns="The JSON Schemas of a new namespace's labels and annotations, and the expiration rules of each "
                     "environment, with an ETag.",
             permission="objects:read",
             response_model=MetadataKeysView, **CONDITIONAL_READ)
def metadata_keys(request: Request, who: Identity = Depends(require("objects:read")),
                  c: AppContext = Depends(ctx)) -> Response:
    """This instance's metadata-keys.yaml as the JSON Schema 2020-12 of a new namespace's labels and annotations: each
    declared key with its rule, which keys are required, which cmapi fills in (x-cmapi-derived-from), and which only an
    operator (namespaces:protect) may set. The same schemas as NamespaceCreate in the API document, here also when
    docs.enabled is false. Each property carries x-cmapi-rule, the rule in the words of a refusal, and title when the file
    gives one. x-cmapi-expiration is expiresAt's: each served environment's expiration rules (expiration.yaml).

    Each property also carries x-cmapi-edit, how the key may change on an existing namespace (#481): `mode` fixed (part of
    the namespace's fixed name), automatic (filled in by cmapi), required or optional, the `reason` a person sees, and
    `sensitive` when a change of it adds one approval. One answer, the same for a create and a change.

    cmapi checks every request against the file itself: this answer describes the rules, it does not replace them. The
    answer is the instance's, the same for every caller; it has a strong ETag, and If-None-Match answers 304."""
    body, etag = metadata_keys_document(c.cfg.metadata, c.cfg.expiration,
                                        tuple(c.cfg.raw_instance["instance"]["allowedEnvironments"]))
    # private: the request carries Authorization (RFC 9111, 3.5); no-cache: revalidated before each reuse (5.2.2.4).
    headers = {"ETag": etag, "Cache-Control": "private, no-cache"}
    if etag_matches(", ".join(request.headers.getlist("if-none-match")), etag):
        return Response(status_code=304, headers=headers)
    return Response(body, media_type="application/json", headers=headers)


@router.read("/clusters/{id}:probe", method="POST", summary="Probe one cluster's held credential",
             returns="The cluster's diagnostics after the checks ran again: status, findings, server version and token"
                     " expiry.",
             permission="operations:run",
             problems=["cluster-not-found"], response_model=ClusterView)
def probe(id: ClusterId, who: Identity = Depends(require("operations:run")), c: AppContext = Depends(ctx)) -> dict:
    """Run the relist checks on this cluster's last discovered import and return its current diagnostics.
    No Secret or cluster resource is changed. A known cluster without an import returns its not-imported view."""
    # An import without a configured environment can only be probed by an unrestricted grant.
    if not c.cfg.roles.allowed(who, "operations:run", c.registry.get(id).environment or ""):
        raise Problem(404, "cluster-not-found", f"Unknown cluster {id}")
    return c.registry.probe(id)
