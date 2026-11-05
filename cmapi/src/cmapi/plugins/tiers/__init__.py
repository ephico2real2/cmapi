"""The tiers plugin: GET /tiers from the catalog core/tiers.py reads."""
from __future__ import annotations

from fastapi import Depends, Query

from cmapi.core.context import AppContext
from cmapi.core.docs import DocumentedRouter
from cmapi.core.identity.claims import Identity
from cmapi.core.models import TierCatalogView
from cmapi.routers import ctx, require

router = DocumentedRouter("tiers", prefix="/api/v1")


@router.read("/tiers", summary="The tier catalog", permission="objects:read", response_model=TierCatalogView)
def tiers(environment: str | None = Query(default=None, description="One environment; default every served one"),
          who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """The tiers offered per environment with their quota and LimitRange values, the custom bounds, and the
    catalog hash a rendered quota carries as cmapi.net/tier-hash."""
    return c.cfg.tiers.describe(environment)
