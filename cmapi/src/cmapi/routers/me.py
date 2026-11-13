"""GET /api/v1/me: who is calling and what their roles allow (docs/02, GET /me)."""
from __future__ import annotations

from fastapi import Depends

from cmapi.core.context import AppContext
from cmapi.core.docs import CORE, DocumentedRouter
from cmapi.core.identity.claims import Identity
from cmapi.core.models import ClusterList, Me
from cmapi.routers import caller, ctx, require

router = DocumentedRouter("core", prefix="/api/v1", **CORE)


@router.read("/me", summary="Who am I", permission=None, response_model=Me, problems=["unauthenticated", "idp-unavailable"])
def me(who: Identity = Depends(caller), c: AppContext = Depends(ctx)) -> dict:
    """The caller's identity as cmapi records it, the roles and groups in the token, and the permissions
    each role grants with the environments it covers. The first thing to check when a call returns 403."""
    return {"username": who.username, "kind": who.kind, "client": who.client_id, "roles": sorted(who.roles),
            "groups": sorted(who.groups), "identity": who.record(), "access": c.cfg.roles.describe(who),
            "instance": c.cfg.name}


@router.read("/clusters", summary="Clusters this instance knows", permission="clusters:read", response_model=ClusterList)
def clusters(who: Identity = Depends(require("clusters:read")), c: AppContext = Depends(ctx)) -> dict:
    """Every cluster from clusters.yaml and every imported one, with its import status and the findings
    of the six checks. A cluster with a policy entry but no import Secret shows not-imported."""
    return {"items": [st.view() for st in c.registry.clusters.values()]}
