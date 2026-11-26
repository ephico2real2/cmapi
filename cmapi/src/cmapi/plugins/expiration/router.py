"""The expiration plugin, read side: GET /expirations, the managed namespaces by expiry, on the one list contract
(docs/01, Lists and Namespace expiration). The writes are :extend, :set and :makePermanent of the namespaces plugin.

Where the date is the truth (#318). Git holds the date that cmapi plans from: :extend, :set and :makePermanent read
`cmapi.net/expires-at` from the namespace folder and are guarded by its etag (If-Match). The list reads the same annotation
live from the watch cache, as docs/02 says of the plugin ("Read live; write Git") and as GET /quotas does: a read of Git for
every namespace of every cluster is one Git read per row. The two agree because the only writer of the annotation is a
cmapi request, and that request holds the namespace (`openRequest`, one open request per namespace) from its plan until the
cluster has the new date (synced). While a request is open the row says so and a change is refused with 409 change-pending;
and a change planned on a date that Git no longer has is refused with 412 by its etag. The database is not a source of the
date: it records the notices sent for a date (`expiration_notices`, written by the worker's expire_check), which is what
`noticesSent` counts.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any, Callable, Mapping

from fastapi import Depends, Query
from sqlalchemy import func, select

from cmapi import __version__
from cmapi.core.context import AppContext
from cmapi.core.db.models import ExpirationNoticeRow
from cmapi.core.db.repo import RequestRepo
from cmapi.core.docs import DocumentedRouter
from cmapi.core.errors import Problem
from cmapi.core.identity.claims import Identity
from cmapi.core.listquery import Lister, ListQuery, Sorts
from cmapi.core.models import ExpirationPage
from cmapi.core.observability import log
from cmapi.plugins.expiration.rules import ExpiryInfo, utc_day, utc_today
from cmapi.routers import Cursor, Limit, ctx, require

router = DocumentedRouter("expiration", prefix="/api/v1", version=__version__, group="Namespaces and metadata",
                          description="The managed namespaces by expiry: a paged list of each namespace that can expire, with its "
                                      "date, the days left and its state. A date is changed with :extend, :set or :makePermanent "
                                      "of the namespaces plugin.")

# The mockup's "most urgent first" (mockups/portal/Main.dc.html, EXP_STATE): grace, expiring, pending_delete, active, permanent.
URGENCY = {"grace": 0, "expiring": 1, "pending_delete": 2, "active": 3, "permanent": 4}
NO_DATE = 99_999                              # a permanent namespace sorts after every date
STATES: dict[str, Callable[[Mapping[str, Any]], bool]] = {
    "attention": lambda r: r["state"] in ("expiring", "grace", "pending_delete"),
    **{s: (lambda r, s=s: r["state"] == s) for s in ("expiring", "grace", "pending_delete", "active", "permanent")},
}
# The Lister's other sorts put the highest value first, so the key is negated: the most urgent state, then the fewest days left.
SORTS = Sorts({"urgency": lambda r: -float(URGENCY[r["state"]] * 1_000_000 + (NO_DATE if r["daysLeft"] is None else r["daysLeft"]))})

Text = Annotated[str, Query(examples=["payments"],
                            description="Text that the name, the team label or the app label contains. Case does not matter.")]
Env = Annotated[str | None, Query(examples=["dev"], description="Only the namespaces of this environment (`cmapi.net/env`).")]
ClusterFilter = Annotated[str | None, Query(alias="clusterId", examples=["CRC"], description="Only the namespaces on this cluster.")]
Team = Annotated[str | None, Query(examples=["payments"], description="Only the namespaces of this team (`cmapi.net/team`).")]
State = Annotated[str | None, Query(examples=["attention"],
                                    description="Only the namespaces in one state: `permanent`, `active`, `expiring`, `grace` or "
                                                "`pending_delete`, or `attention` for the three that need action (expiring, grace "
                                                "and pending_delete). Another value returns 422 `validation-failed`.")]
Sort = Annotated[str, Query(examples=["urgency"],
                            description="`urgency` puts the most urgent first: grace, expiring, pending_delete, active, then "
                                        "permanent, and in each the fewest days left first. `name` sorts by name, A to Z.")]


def today() -> date:
    """The day that the list counts from: the UTC date, the same day as the pipeline's plan of :extend and :set and the
    daily expire_check (`utc_today`, #321). A test fixes the list's day here."""
    return utc_today()


def _created(meta: Mapping[str, Any]) -> date | None:
    return utc_day(meta.get("creationTimestamp"))


def _expires(cluster_id: str, name: str, raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        # Only the renderer writes the key, and no Kyverno policy checks its value here; prod's namespaces never carry it
        # (deny-expiry-in-prod). A hand-edited value that is not a date is shown as the cluster has it and counted as no
        # date, because no plan can extend it; the log names it for the platform team.
        log.warning("expires_at_unreadable", cluster_id=cluster_id, namespace=name, value=raw[:40])
        return None


def _notices(c: AppContext) -> dict[tuple[str, str, str], int]:
    """(cluster, namespace, date) -> the notices sent before that date (thresholds 14, 7 and 1, not grace or delete)."""
    with c.db.session() as s:
        q = (select(ExpirationNoticeRow.cluster_id, ExpirationNoticeRow.namespace, ExpirationNoticeRow.expires_at,
                    func.count(func.distinct(ExpirationNoticeRow.threshold_days)))
             .where(ExpirationNoticeRow.ok.is_(True), ExpirationNoticeRow.threshold_days > 0)
             .group_by(ExpirationNoticeRow.cluster_id, ExpirationNoticeRow.namespace, ExpirationNoticeRow.expires_at))
        return {(cl, ns, at): n for cl, ns, at, n in s.execute(q)}


def actions_of(expiration_on: bool, expires: date | None) -> list[str]:
    """The expiry writes that a row's namespace takes: :extend and :makePermanent with a date, :set without one. Where
    expiration is off, only :makePermanent of a date given while it was on (#479, the coordinator's ruling on F02)."""
    if not expiration_on:
        return ["makePermanent"] if expires else []
    return ["extend", "makePermanent"] if expires else ["set"]


def expiration_rows(c: AppContext, who: Identity, day: date) -> tuple[list[dict[str, Any]], set[str]]:
    """Each managed namespace that can expire, in an environment where the caller holds objects:read, and the environments
    whose expiration is on. Where it is off, only a namespace that kept a date is listed, so it can be made permanent."""
    with c.db.session() as s:
        open_map = RequestRepo(s).open_namespaces()
    notices = _notices(c)
    rows: list[dict[str, Any]] = []
    envs: set[str] = set()
    for st in c.registry.connected():
        env = st.policy.environment if st.policy else None
        if env is None or not c.cfg.roles.allowed(who, "objects:read", env):
            continue
        cache = st.cache                    # once: the registry clears it when the cluster drops, after `connected()` (#402)
        if cache is None:
            continue
        on = c.cfg.expiration.allows(env)
        rules = c.cfg.expiration.rules(env) if on else None
        if on:
            envs.add(env)
        for ns in cache.all("Namespace"):
            m = ns["metadata"]
            labels, ann = m.get("labels") or {}, m.get("annotations") or {}
            if labels.get("cmapi.net/managed") != "true":
                continue
            raw = ann.get("cmapi.net/expires-at")
            expires, created = _expires(st.cluster_id, m["name"], raw), _created(m)
            if not on and expires is None:
                continue                    # expiration is off here: nothing to show but a kept date
            # Where expiration is off a kept date is not acted on (no notice, no delete), so its state is permanent.
            state = c.cfg.expiration.state(ExpiryInfo(m["name"], env, created or day, expires), day)
            rows.append({"name": m["name"], "clusterId": st.cluster_id, "env": labels.get("cmapi.net/env") or env,
                         "team": labels.get("cmapi.net/team"), "app": labels.get("cmapi.net/app"), "created": created,
                         "expiresAt": raw, "daysLeft": (expires - day).days if expires else None, "state": state,
                         "graceEnds": expires + timedelta(days=rules.grace_days) if expires and rules else None,
                         "lifetimeDays": (expires - created).days if expires and created else None,
                         "noticesSent": notices.get((st.cluster_id, m["name"], raw), 0) if expires else 0,
                         "openRequest": open_map.get((st.cluster_id, m["name"])), "actions": actions_of(on, expires)})
    return rows, envs


def _rules_view(c: AppContext, env: str) -> dict[str, Any]:
    r = c.cfg.expiration.rules(env)
    return {"maxExtensionDays": r.max_extension_days, "maxLifetimeDays": r.max_lifetime_days,
            "notifyDaysBefore": list(r.notify_days_before), "graceDays": r.grace_days}


@router.read("/expirations", summary="List namespaces by expiry",
             returns="One page of the namespaces that can expire, with their dates, days left and notices, the count "
                     "of each state, and each environment's rules.",
             permission="objects:read", response_model=ExpirationPage,
             problems=["invalid-cursor", "invalid-sort", "invalid-limit", "validation-failed"])
def expirations(q: Text = "", env: Env = None, cluster_id: ClusterFilter = None, team: Team = None, state: State = None,
                sort: Sort = "urgency", limit: Limit = 50, cursor: Cursor = None,
                who: Identity = Depends(require("objects:read")), c: AppContext = Depends(ctx)) -> dict:
    """One page of the managed namespaces that can expire, in the caller's environments: each one's expiry date from the
    watch cache, the days left, its state and the notices sent, the count of each state over the other filters, and the
    rules of each environment. Where expiration is off (no entry in expiration.yaml, or enabled: false, such as prod), only a
    namespace that kept a date from before is listed, with :makePermanent as its one action, and the environment has no
    rules. `today` is the day the API counts from."""
    if state and state not in STATES:
        raise Problem.unprocessable("validation-failed", f"state is one of {sorted(STATES)}, not {state}")
    day = today()
    rows, envs = expiration_rows(c, who, day)
    # The day is bound into the cursor: daysLeft and state, so the urgency order, move at midnight, and a cursor of another
    # day would skip or repeat rows. It is refused with 400 invalid-cursor, and the portal goes back to the first page.
    query = ListQuery(q=q, filters={"env": env or "", "clusterId": cluster_id or "", "team": team or ""}, sort=sort, limit=limit,
                      cursor=cursor, context={"state": state or "", "today": day.isoformat()})
    lister = Lister(c.lister.secret, SORTS)
    page = lister.page([r for r in rows if STATES[state](r)] if state else rows, query)
    # The counts are over the other filters, not over the chosen state: each chip keeps its number.
    others = lister.filtered(rows, query)
    page["facets"] = {name: sum(1 for r in others if test(r)) for name, test in STATES.items()}
    page["rules"] = {e: _rules_view(c, e) for e in sorted(envs)}
    page["today"] = day
    return page
