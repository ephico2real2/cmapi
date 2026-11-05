"""The quotas plugin, read side: GET /quotas, :suggest and :export over the watch cache, on the one
list contract (docs/01, Lists). Writes are a tier or quota PATCH on the namespace."""
from __future__ import annotations

from typing import Any

from fastapi import Depends, Query
from fastapi.responses import StreamingResponse

from cmapi.core.context import AppContext
from cmapi.core.db.repo import AuditRepo, RequestRepo
from cmapi.core.docs import DocumentedRouter
from cmapi.core.identity.claims import Identity
from cmapi.core.listquery import ListQuery
from cmapi.core.models import QuotaPage, Suggestions
from cmapi.core.tiers import qty
from cmapi.routers import ctx, require

router = DocumentedRouter("quotas", prefix="/api/v1")
COLUMNS = ["name", "clusterId", "env", "team", "tier", "cpuUsed", "cpuHard", "memoryUsed", "memoryHard", "podsUsed", "podsHard",
           "used", "expiresAt", "tierOutdated"]


def quota_rows(c: AppContext, who: Identity) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with c.db.session() as s:
        open_map = RequestRepo(s).open_namespaces()
    for st in c.registry.connected():
        env = st.policy.environment if st.policy else None
        if env is None or not c.cfg.roles.allowed(who, "objects:read", env):
            continue
        cache = st.cache
        quotas = {q["metadata"]["namespace"]: q for q in cache.all("ResourceQuota")
                  if (q["metadata"].get("labels") or {}).get("cmapi.net/managed") == "true"}
        for ns in cache.all("Namespace"):
            m = ns["metadata"]
            labels, ann = m.get("labels") or {}, m.get("annotations") or {}
            if labels.get("cmapi.net/managed") != "true":
                continue
            q = quotas.get(m["name"], {})
            hard, used = q.get("spec", {}).get("hard", {}), q.get("status", {}).get("used", {})

            def pct(k: str) -> float:
                return float(qty(used.get(k, "0")) / qty(hard[k])) if k in hard and qty(hard[k]) else 0.0

            tier = labels.get("cmapi.net/tier")
            tier_hash = (q.get("metadata", {}).get("annotations") or {}).get("cmapi.net/tier-hash")
            rows.append({"name": m["name"], "clusterId": st.cluster_id, "env": labels.get("cmapi.net/env"),
                         "team": labels.get("cmapi.net/team"), "app": labels.get("cmapi.net/app"), "tier": tier,
                         "cpu": [used.get("requests.cpu", "0"), hard.get("requests.cpu")],
                         "memory": [used.get("requests.memory", "0"), hard.get("requests.memory")],
                         "pods": [used.get("pods", "0"), hard.get("pods")],
                         "used": max(pct("requests.cpu"), pct("requests.memory"), pct("pods")),
                         "expiresAt": ann.get("cmapi.net/expires-at"), "tierHash": tier_hash,
                         "tierOutdated": bool(tier and env and c.cfg.tiers.is_outdated(env, tier, tier_hash)),
                         "openRequest": open_map.get((st.cluster_id, m["name"]))})
    return rows


FACETS = {"near-limit": lambda r: r["used"] >= 0.8, "tier-outdated": lambda r: r["tierOutdated"],
          "open-request": lambda r: bool(r.get("openRequest"))}


def _query(q: str, env: str | None, cluster_id: str | None, team: str | None, tier: str | None, sort: str, limit: int,
           cursor: str | None, starts_with: str | None) -> ListQuery:
    return ListQuery(q=q, filters={"env": env or "", "clusterId": cluster_id or "", "team": team or "", "tier": tier or ""},
                     sort=sort, limit=limit, cursor=cursor, starts_with=starts_with)


@router.read("/quotas", summary="Every namespace's quota, paged", permission="objects:read", response_model=QuotaPage,
             problems=["invalid-cursor", "invalid-sort", "invalid-limit"])
def quotas(q: str = Query(default="", description="Match on name, team or app"),
           env: str | None = Query(default=None, description="Environment"),
           cluster_id: str | None = Query(default=None, alias="clusterId", description="Cluster"),
           team: str | None = Query(default=None, description="cmapi.net/team"),
           tier: str | None = Query(default=None, description="Tier"),
           sort: str = Query(default="name", description="name or used"),
           limit: int = Query(default=50, description="25, 50 or 100; at most 200"),
           cursor: str | None = Query(default=None, description="Keyset cursor"),
           starts_with: str | None = Query(default=None, alias="startsWith", description="Letter jump with sort=name"),
           who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """One page of managed namespaces in the caller's environments with hard and used requests.cpu,
    requests.memory and pods from the watch cache, their tier, whether the catalog moved on (tier-outdated),
    and the attention counts over the current filters."""
    return c.lister.page(quota_rows(c, who), _query(q, env, cluster_id, team, tier, sort, limit, cursor, starts_with),
                         facets=FACETS)


@router.read("/quotas:suggest", summary="Type-ahead matches", permission="objects:read", response_model=Suggestions)
def suggest(q: str = Query(default="", description="Two or more characters"), who: Identity = Depends(require("objects:read")),
            c: AppContext = Depends(ctx)) -> dict:
    """Up to ten namespaces whose name starts with the text, then contains it, then whose team or app label matches."""
    return {"items": c.lister.suggest(quota_rows(c, who), q)}


@router.read("/quotas:export", summary="Export the quota list as CSV", permission="objects:read", response_model=None)
def export(q: str = Query(default="", description="Match on name, team or app"),
           env: str | None = Query(default=None, description="Environment"),
           cluster_id: str | None = Query(default=None, alias="clusterId", description="Cluster"),
           team: str | None = Query(default=None, description="cmapi.net/team"),
           tier: str | None = Query(default=None, description="Tier"),
           sort: str = Query(default="name", description="name or used"),
           who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)):
    """Every row matching the same filters in the same order, capped at 10,000 rows, written to the audit log."""
    rows = [{**r, "cpuUsed": r["cpu"][0], "cpuHard": r["cpu"][1], "memoryUsed": r["memory"][0], "memoryHard": r["memory"][1],
             "podsUsed": r["pods"][0], "podsHard": r["pods"][1]} for r in quota_rows(c, who)]
    with c.db.session() as s:
        AuditRepo(s).record(who, "quotas.export", "csv", {"rows": len(rows), "q": q, "env": env, "clusterId": cluster_id})
    query = _query(q, env, cluster_id, team, tier, sort, 50, None, None)
    return StreamingResponse(c.lister.export_csv(rows, query, COLUMNS), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="quotas.csv"'})
