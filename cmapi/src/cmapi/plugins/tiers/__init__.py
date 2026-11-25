"""The tiers plugin: GET /tiers from the catalog core/tiers.py reads."""
from __future__ import annotations

from fastapi import Depends, Query

from cmapi import __version__
from cmapi.core.config import environment_not_served
from cmapi.core.context import AppContext
from cmapi.core.docs import DocumentedRouter
from cmapi.core.identity.claims import Identity
from cmapi.core.models import TierCatalogView
from cmapi.routers import ctx, require

router = DocumentedRouter("tiers", prefix="/api/v1", version=__version__, group="Capacity and placement",
                          description="The tier catalog: the quota and LimitRange values that each environment offers.")


@router.read("/tiers", summary="Get the tier catalog",
             returns="The tiers of each environment asked for, the catalog's hash, and what a request may size or "
                     "override.",
             permission="objects:read", response_model=TierCatalogView,
             problems=["environment-not-served"])
def tiers(environment: str | None = Query(default=None, examples=["dev"],
                                              description="Only this environment. Without it, the answer has each environment "
                                                          "that the instance serves. One the instance does not serve returns "
                                                          "422 `environment-not-served`."),
          who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """The tiers offered per environment with their quota and LimitRange values, the custom bounds, and the
    catalog hash a rendered quota carries as cmapi.net/tier-hash."""
    if environment and environment not in c.cfg.allowed_environments:    # describe() reads "" as every environment
        raise environment_not_served(c.cfg, environment)
    return c.cfg.tiers.describe(environment)
