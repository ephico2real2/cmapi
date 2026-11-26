"""The quotas plugin, read side: GET /quotas, :suggest and :export over the watch cache, on the one
list contract (docs/01, Lists). Writes are a tier or quota PATCH on the namespace.

Each row carries its usage verdict from the latest daily sweep (capacity/sweep.py, #310), read in one query and joined in
memory: docs/01, "Rows come from the watch cache joined in memory with the latest verdicts and recommendations; nothing calls
Thanos and nothing queries the database per row". Recommendations are docs/03's phase 6 and not built."""
from __future__ import annotations

from typing import Annotated, Any, Iterator

from fastapi import Depends, Query, Request
from fastapi.responses import StreamingResponse

from cmapi import __version__
from cmapi.capacity.sweep import VerdictRepo, row_verdict
from cmapi.capacity.verdicts import VERDICTS
from cmapi.core.context import AppContext
from cmapi.core.db.repo import AuditRepo, RequestRepo
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.listquery import ListQuery, severity
from cmapi.core.models import QuotaPage, Suggestions
from cmapi.core.tiers import qty
from cmapi.routers import Cursor, Limit, ctx, require

router = DocumentedRouter("quotas", prefix="/api/v1", version=__version__, group="Capacity and placement",
                          description="The quota of each managed namespace on every cluster of the instance: a paged list, "
                                      "type-ahead matches and a CSV export.")
# The filters that the list and its export share, so that an export returns the rows that the list shows.
Text = Annotated[str, Query(examples=["payments"],
                            description="Text that the name, the team label or the app label contains. Case does not matter.")]
Env = Annotated[str | None, Query(examples=["dev"], description="Only the namespaces of this environment (`cmapi.net/env`).")]
ClusterFilter = Annotated[str | None, Query(alias="clusterId", examples=["CRC"], description="Only the namespaces on this cluster.")]
Team = Annotated[str | None, Query(examples=["payments"], description="Only the namespaces of this team (`cmapi.net/team`).")]
Tier = Annotated[str | None, Query(examples=["small"], description="Only the namespaces of this tier (`cmapi.net/tier`).")]
Sort = Annotated[str, Query(examples=["used"],
                            description="`name` sorts by name, A to Z. `used` puts the highest use first: the largest of "
                                        "CPU, memory and pods, each as used divided by hard. `severity` puts the most urgent "
                                        "first: `quota-tight` or 95% or more, then 80% or more, then `idle`, "
                                        "`quota-oversized` or `requests-oversized`, then the others.")]
State = Annotated[str | None, Query(examples=["near-limit"],
                                    description="Only the namespaces that one attention count of `facets` counts: `quota-tight`, "
                                                "`near-limit`, `oversized`, `idle`, `tier-outdated`, `open-request` or "
                                                "`needs-attention`. Another value returns 422 `validation-failed`.")]
Verdict = Annotated[str | None, Query(examples=["quota-tight"],
                                      description="Only the namespaces whose usage verdict is this one: `quota-tight`, `idle`, "
                                                  "`quota-oversized`, `requests-oversized`, `right-sized` or `insufficient-data`. "
                                                  "Another value returns 422 `validation-failed`.")]

COLUMNS = ["name", "clusterId", "env", "team", "tier", "cpuUsed", "cpuHard", "memoryUsed", "memoryHard", "podsUsed", "podsHard",
           "used", "expiresAt", "tierOutdated", "verdict"]


def quota_rows(c: AppContext, who: Identity) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with c.db.session() as s:
        open_map = RequestRepo(s).open_namespaces()
        verdicts = VerdictRepo(s).latest()
    for st in c.registry.connected():
        env = st.policy.environment if st.policy else None
        if env is None or not c.cfg.roles.allowed(who, "objects:read", env):
            continue
        cache = st.cache                    # once: the registry clears it when the cluster drops, after `connected()` (#402)
        if cache is None:
            continue
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
                         "openRequest": open_map.get((st.cluster_id, m["name"])),
                         **row_verdict(verdicts.get((st.cluster_id, m["name"])), c.usage.configured)})
    return rows


# docs/01, Lists: "facets.attention counts quota-tight, near limit (80% or more of any hard limit), open recommendation,
# oversized, idle and open request". tier-outdated is the catalog's (#301); the recommendation is phase 6 and not built.
FACETS = {"quota-tight": lambda r: r.get("verdict") == "quota-tight", "near-limit": lambda r: r["used"] >= 0.8,
          "oversized": lambda r: r.get("verdict") in ("quota-oversized", "requests-oversized"),
          "idle": lambda r: r.get("verdict") == "idle", "tier-outdated": lambda r: r["tierOutdated"],
          "open-request": lambda r: bool(r.get("openRequest")),
          # The heading's "{N} need attention" (mockups/portal/Main.dc.html, quotaView: severity(x) > 0).
          "needs-attention": lambda r: severity(r["used"], r.get("verdict")) > 0}
# docs/01, Lists: "sort is name (default), used (highest percentage of quota first) or severity". The shared Lister also
# knows `newest`, the request list's order (core/context.py), which a quota row has no time for.
SORTS = ("name", "used", "severity")


def _query(q: str, env: str | None, cluster_id: str | None, team: str | None, tier: str | None, sort: str, limit: int,
           cursor: str | None, starts_with: str | None, state: str | None = None, verdict: str | None = None) -> ListQuery:
    if sort not in SORTS:
        raise Problem.bad_request("invalid-sort", f"Unknown sort {sort}")
    if verdict and verdict not in VERDICTS:
        raise Problem.unprocessable("validation-failed", f"verdict is one of {list(VERDICTS)}, not {verdict}")
    return ListQuery(q=q, filters={"env": env or "", "clusterId": cluster_id or "", "team": team or "", "tier": tier or "",
                                   "verdict": verdict or ""},
                     sort=sort, limit=limit, cursor=cursor, starts_with=starts_with, context={"state": state or ""})


def _in_state(rows: list[dict[str, Any]], state: str | None) -> list[dict[str, Any]]:
    """The rows that one attention count covers. The counts in `facets` stay those of the other filters, so the chips keep their numbers."""
    if not state:
        return rows
    if state not in FACETS:
        raise Problem.unprocessable("validation-failed", f"state is one of {sorted(FACETS)}, not {state}")
    return [r for r in rows if FACETS[state](r)]


@router.read("/quotas", summary="List namespace quotas",
             returns="One page of namespaces with their quota, used and hard, the attention counts, and the cursors of"
                     " the pages beside it.",
             permission="objects:read", response_model=QuotaPage,
             problems=["invalid-cursor", "invalid-sort", "invalid-limit", "validation-failed"])
def quotas(q: Text = "", env: Env = None, cluster_id: ClusterFilter = None, team: Team = None, tier: Tier = None,
           state: State = None, verdict: Verdict = None, sort: Sort = "name", limit: Limit = 50, cursor: Cursor = None,
           starts_with: str | None = Query(default=None, alias="startsWith", examples=["p"],
                                           description="With `sort=name`, the page starts at the first name at or after this "
                                                       "text. Use it to jump to a letter."),
           who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """One page of managed namespaces in the caller's environments with hard and used requests.cpu,
    requests.memory and pods from the watch cache, their tier, whether the catalog moved on (tier-outdated), their usage
    verdict from the latest daily sweep, and the attention counts over the current filters."""
    rows = quota_rows(c, who)
    query = _query(q, env, cluster_id, team, tier, sort, limit, cursor, starts_with, state, verdict)
    page = c.lister.page(_in_state(rows, state), query, facets=FACETS)
    if state:
        # The attention counts are over the other filters, not over the chosen state: each chip keeps its number.
        page["facets"] = {name: sum(1 for r in c.lister.filtered(rows, query) if test(r)) for name, test in FACETS.items()}
    return page


@router.read("/quotas:suggest", summary="List quota search suggestions",
             returns="Up to ten namespaces that match the text, each with why it matched.",
             permission="objects:read", response_model=Suggestions)
def suggest(q: str = Query(default="", examples=["pay"],
                           description="The text to match. Fewer than two characters return no match."), who: Identity = Depends(require("objects:read")),
            c: AppContext = Depends(ctx)) -> dict:
    """Up to ten namespaces whose name starts with the text, then contains it, then whose team or app label matches."""
    return {"items": c.lister.suggest(quota_rows(c, who), q)}


@router.read("/quotas:export", summary="Export the quota list as CSV",
             returns="Every row of the quota list with the same filters, in the same order, as CSV: at most 10,000 "
                     "rows.",
             permission="objects:read", media_type="text/csv", problems=["invalid-sort", "validation-failed"])
def export(request: Request, q: Text = "", env: Env = None, cluster_id: ClusterFilter = None, team: Team = None,
           tier: Tier = None, state: State = None, verdict: Verdict = None, sort: Sort = "name",
           who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)):
    """Every row matching the same filters in the same order, capped at 10,000 rows, written to the audit log."""
    # A HEAD (main.py, _serve_head_with_get, #605) sends no rows, so it exports nothing: no audit event, and no CSV made to be
    # dropped. RFC 9110, section 9.3.2: HEAD gets the metadata "without transferring its representation data", and skipping
    # "generating and discarding the content for a HEAD request" is "preferable". The docstring is the API document's text.
    head = request.method == "HEAD"
    rows = [{**r, "cpuUsed": r["cpu"][0], "cpuHard": r["cpu"][1], "memoryUsed": r["memory"][0], "memoryHard": r["memory"][1],
             "podsUsed": r["pods"][0], "podsHard": r["pods"][1]} for r in quota_rows(c, who)]
    # The refusals first, for both methods (a sort, 400; a state, 422): a refused export is no export, so it writes no audit
    # event, and the refusal is sent before a stream's 200.
    query = _query(q, env, cluster_id, team, tier, sort, 50, None, None, state, verdict)
    selected = _in_state(rows, state)
    lines: Iterator[str] = iter(())
    if not head:
        lines = c.lister.export_csv(selected, query, COLUMNS)
        with c.db.session() as s:
            AuditRepo(s).record(who, "quotas.export", "csv", {"rows": len(rows), "q": q, "env": env, "clusterId": cluster_id})
    return StreamingResponse(lines, media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="quotas.csv"'})
