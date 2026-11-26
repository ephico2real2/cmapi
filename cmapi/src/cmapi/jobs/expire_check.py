"""expire_check: daily. The notices before a namespace's expiry date, its grace, and the delete request after grace (#263).

The design, docs/01 "Namespace expiration": "The worker notifies the team DL (cmapi.net/team-dl) through the Notifier at 14, 7
and 1 days. On the date the namespace enters grace: it keeps running, can still be extended, and is flagged on the Expiration
tab. After grace, cmapi opens a delete request approved by the expired-namespace policy, whose guards are no open request on
the namespace, not protected, no extension in the last 24 hours, and at least two notices sent." docs/02, "Held expiry
deletes": "When a guard fails (open request, protected, recent extension, too few notices), expire_check does not open the
delete; it lists the namespace for action and tries again the next day."

Each run, for each connected cluster that takes writes, in an environment this instance serves and whose expiration is on
(prod never is):

1. It reads each managed Namespace that carries `cmapi.net/expires-at` from the watch cache, as GET /expirations does, and
   from the database the notices already recorded for that date (`expiration_notices`), the open requests and the last
   extension request. `ExpirationRules.expire_check` decides, on the UTC day (`utc_today`, #321).
2. A notice goes to the team DL (`cmapi.net/team-dl`) by email when integrations.yaml sets `notifier.smtp.host`. Without it
   no message leaves cmapi: the notice is recorded with the channel `portal`, and the Expiration tab shows it (`noticesSent`),
   as approval prompts are recorded when there is no SMTP (jobs/channel_notify.py). A failed email is recorded with ok false,
   is not counted, and is sent again on the next run.
3. A namespace in grace gets a grace row once (threshold 0) for its date.
4. After grace, the delete is the normal delete request (`Pipeline.plan_expiry_delete`, then `submit`): the approval rules
   decide it (the expired-namespace policy, or the environment's delete rule with approvers), a bot PR removes the folder, and
   Argo CD waits for an operator's prune confirmation (awaiting_prune). Nothing here deletes anything on a cluster. The row
   that records it has threshold -1 and the request's ID: one delete request per expiry date. A request that people reject
   or cancel, or that fails, is not opened again for the same date; the namespace stays listed (pending_delete) for action,
   and a new date (an extension) starts a new cycle. A namespace extended in the last 24 hours, by the clock and not by
   the day, is held, as is one whose live object does not carry Prune=confirm (Pipeline.plan_expiry_delete).

Each action has its own transaction, fenced by this job's lease (JobRepo.fence): a worker whose lease was taken over sends
nothing and records nothing, and while one action runs nobody can claim the job. The jobs table holds at most one pending
expire_check (uq_jobs_pending) and SKIP LOCKED gives it to one worker, so several replicas give one result. Each action also
takes a transaction lock on its namespace (pg_advisory_xact_lock) and then reads its row again, so two runs at once or a
second run the same day send no notice twice. A notice is delivered at least once, not exactly once: the row is committed
after the relay accepts the message, so a worker lost between the two sends it again on the next run. That is the
transactional outbox's guarantee, and RFC 5321's (section 4.5.3.2.6: a lost reply "would typically result in delivery of
multiple copies"); a second email is the cheaper failure than a notice never sent or never counted. A namespace that
fails is logged and counted and does not stop the others; the next run comes in EXPIRE_CHECK_RETRY seconds instead of a day
when any part of the run could not be done.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from cmapi.core.channels import EmailNotifier, notifier_for
from cmapi.core.context import AppContext
from cmapi.core.db.models import ChangeRequestRow, ExpirationNoticeRow, JobRow
from cmapi.core.db.repo import JobRepo, LeaseLost, RequestRepo, utcnow
from cmapi.core.errors import Problem
from cmapi.core.observability import EXPIRY_ACTIONS, log
from cmapi.core.pipeline import EXPIRY_REQUESTER
from cmapi.plugins.expiration.rules import ExpiryInfo, utc_day, utc_today

EXPIRE_CHECK_EVERY = 86_400       # docs/02, Worker jobs: daily
EXPIRE_CHECK_RETRY = 900          # the next run after a run that could not finish: a stale cache, a failed email or delete
GRACE, DELETE = 0, -1             # expiration_notices.threshold_days of the grace row and the delete row
EXTENSION_REASONS = ("expiration:extend", "expiration:set")
GUARD_FACTS = ("openRequestOnNamespace", "noticesSent", "lastExtensionHoursAgo")


def expire_check(ctx: AppContext, s: Session, job: JobRow) -> None:
    complete = check(ctx, utc_today(), lease=s.info.get("lease"))
    jobs = JobRepo(s)
    jobs.done(job)
    jobs.enqueue("expire_check", delay=EXPIRE_CHECK_EVERY if complete else EXPIRE_CHECK_RETRY,
                 payload={"every": EXPIRE_CHECK_EVERY})


def check(ctx: AppContext, day: date, *, lease: tuple[int, str, int] | None = None) -> bool:
    """One pass over every cluster on `day`; True when every part of it was done."""
    complete = True
    notifier = notifier_for(ctx)
    for st in ctx.registry.connected():
        policy = st.policy
        if policy is None or not policy.writes:
            continue                              # no GitOps folder: cmapi cannot delete there, so it gives no notice either
        env = policy.environment
        if env not in ctx.cfg.allowed_environments or not ctx.cfg.expiration.allows(env):
            continue                              # prod, or expiration off: a kept date is not acted on (docs/01)
        cache = st.cache                          # once: the registry may clear it meanwhile (#402)
        if cache is None or cache.kind_stale("Namespace")[0]:
            log.warning("expire_check_cluster_skipped", cluster_id=st.cluster_id, reason="no fresh list of its namespaces")
            complete = False
            continue
        complete = _check_cluster(ctx, lease, notifier, st.cluster_id, env, cache.all("Namespace"), day) and complete
    return complete


def _check_cluster(ctx: AppContext, lease: Any, notifier: EmailNotifier | None, cluster_id: str, env: str,
                   namespaces: list[Mapping[str, Any]], day: date) -> bool:
    dated: dict[str, tuple[Mapping[str, Any], date]] = {}
    for obj in namespaces:
        meta = obj.get("metadata") or {}
        if (meta.get("labels") or {}).get("cmapi.net/managed") != "true":
            continue
        expires = _date((meta.get("annotations") or {}).get("cmapi.net/expires-at"))
        if expires is not None:
            dated[meta["name"]] = (meta, expires)
    if not dated:
        return True
    with ctx.db.session() as s:
        recorded = _recorded_thresholds(s, cluster_id)
        open_map = RequestRepo(s).open_namespaces(cluster_id)
        extended = _last_extensions(s, cluster_id)
    infos = [ExpiryInfo(name, env, created=utc_day(meta.get("creationTimestamp")) or day, expires_at=expires,
                        notices_sent=frozenset(t for t in recorded.get((name, expires.isoformat()), ()) if t > 0),
                        last_extension=extended[name].date() if name in extended else None,
                        open_request=(cluster_id, name) in open_map,
                        protected=ctx.cfg.approvals.is_protected(meta.get("labels") or {}))
             for name, (meta, expires) in sorted(dated.items())]
    rules = ctx.cfg.expiration
    result = rules.expire_check(infos, day)
    complete = True

    def act(name: str, action: str, fn: Any, *args: Any) -> None:
        nonlocal complete
        try:
            complete = fn(*args) and complete
        except LeaseLost:
            raise                                                   # another worker runs the job now: stop, record nothing
        except Exception as exc:                                    # noqa: BLE001 - one namespace never stops the others
            complete = False
            EXPIRY_ACTIONS.labels("error", env).inc()
            log.error("expire_check_failed", cluster_id=cluster_id, namespace=name, action=action,
                      error=f"{type(exc).__name__}: {exc}"[:300])

    for name, threshold in result.notify:
        meta, expires = dated[name]
        act(name, "notice", _notice, ctx, lease, notifier, cluster_id, env, meta, expires, threshold, day)
    for info in infos:
        if rules.state(info, day) == "grace" and GRACE not in recorded.get((info.namespace, info.expires_at.isoformat()), ()):
            act(info.namespace, "grace", _grace, ctx, lease, cluster_id, env, info.namespace, info.expires_at)
    for facts in result.open_delete:
        name = facts["namespace"]
        guard_facts = {k: facts[k] for k in GUARD_FACTS}
        if name in extended:                      # the policy guard reads hours; the reference check counts whole days
            guard_facts["lastExtensionHoursAgo"] = int((utcnow() - extended[name]).total_seconds() // 3600)
        act(name, "delete", _open_delete, ctx, lease, cluster_id, env, name, dated[name][1], guard_facts)
    for name, guard in result.held:
        EXPIRY_ACTIONS.labels("delete_held", env).inc()
        log.info("expiry_delete_held", cluster_id=cluster_id, namespace=name, guard=guard, expires_at=dated[name][1].isoformat())
    return complete


def _notice(ctx: AppContext, lease: Any, notifier: EmailNotifier | None, cluster_id: str, env: str,
            meta: Mapping[str, Any], expires: date, threshold: int, day: date) -> bool:
    name = meta["name"]
    dl = (meta.get("annotations") or {}).get("cmapi.net/team-dl")
    with ctx.db.session() as s:
        _fence(s, lease)                          # a message is a side effect no rollback undoes: a stale worker sends none
        _lock_namespace(s, cluster_id, name)
        if _is_recorded(s, cluster_id, name, expires, threshold):
            return True
        if notifier is not None and dl:
            subject, body, links = _message(ctx, cluster_id, env, name, expires, day)
            try:
                notifier.send([dl], subject, body, links)
                ok, detail = True, f"email to {dl}"
            except Exception as exc:                                # noqa: BLE001 - recorded, not counted, sent again
                ok, detail = False, f"email to {dl} failed: {type(exc).__name__}: {exc}"[:300]
        else:
            why = "no SMTP host in integrations.yaml" if notifier is None else "the namespace names no cmapi.net/team-dl"
            ok, detail = True, f"portal: the Expiration tab; no email ({why})"
        s.add(ExpirationNoticeRow(cluster_id=cluster_id, namespace=name, expires_at=expires.isoformat(),
                                  threshold_days=threshold, ok=ok, detail=detail))
    EXPIRY_ACTIONS.labels("notice" if ok else "notice_failed", env).inc()
    log.info("expiry_notice", cluster_id=cluster_id, namespace=name, threshold_days=threshold, expires_at=expires.isoformat(),
             ok=ok, channel="email" if detail.startswith("email") else "portal")
    return ok


def _grace(ctx: AppContext, lease: Any, cluster_id: str, env: str, name: str, expires: date) -> bool:
    grace_days = ctx.cfg.expiration.rules(env).grace_days
    with ctx.db.session() as s:
        _fence(s, lease)
        _lock_namespace(s, cluster_id, name)
        if _is_recorded(s, cluster_id, name, expires, GRACE):
            return True
        s.add(ExpirationNoticeRow(cluster_id=cluster_id, namespace=name, expires_at=expires.isoformat(), threshold_days=GRACE,
                                  detail=f"grace ends on {(expires + timedelta(days=grace_days)).isoformat()}"))
    EXPIRY_ACTIONS.labels("grace", env).inc()
    log.info("expiry_grace", cluster_id=cluster_id, namespace=name, expires_at=expires.isoformat())
    return True


def _open_delete(ctx: AppContext, lease: Any, cluster_id: str, env: str, name: str, expires: date,
                 guard_facts: Mapping[str, Any]) -> bool:
    """The normal delete request, through the pipeline. A refusal (another request holds the namespace, it is protected, its
    date moved, Git or the cluster cannot be read) holds the delete until the next run, as a failed guard does."""
    grace_days = ctx.cfg.expiration.rules(env).grace_days
    try:
        plan = ctx.pipeline.plan_expiry_delete(cluster_id, name, expires_at=expires, facts=guard_facts)
        with ctx.db.session() as s:
            _fence(s, lease)
            _lock_namespace(s, cluster_id, name)
            # Read again under the lock, as the notices are: the scan's snapshot can be minutes old by now.
            if _is_recorded(s, cluster_id, name, expires, DELETE):
                raise Problem.conflict("expiry-delete-already-opened",
                                       f"A delete request was opened for the expiry {expires.isoformat()} of {name}")
            last = _last_extensions(s, cluster_id, name).get(name)
            if last is not None and utcnow() - last < timedelta(hours=24):
                # docs/01: "no extension in the last 24 hours". By the clock: the reference check counts whole UTC days, so
                # an extension asked at 23:30 passes it at 00:30.
                raise Problem.conflict("noExtensionInLast24h", f"An extension of {name} was asked at {last.isoformat()}")
            key = f"expired:{cluster_id}/{name}@{expires.isoformat()}"
            row = ctx.pipeline.submit(EXPIRY_REQUESTER, plan, RequestRepo(s), JobRepo(s), idempotency_key=None,
                                      body_fingerprint=hashlib.sha256(key.encode()).hexdigest(),
                                      justification=f"{name} expired on {expires.isoformat()}; its {grace_days} days of grace "
                                                    "are over. Opened by expire_check.")
            s.add(ExpirationNoticeRow(cluster_id=cluster_id, namespace=name, expires_at=expires.isoformat(),
                                      threshold_days=DELETE, request_id=row.request_id, detail=f"delete request {row.status}"))
            request_id, status, approval = row.request_id, row.status, (row.requirement or {}).get("auto")
    except Problem as exc:
        EXPIRY_ACTIONS.labels("delete_held", env).inc()
        log.info("expiry_delete_held", cluster_id=cluster_id, namespace=name, guard=exc.code, detail=exc.detail[:200],
                 expires_at=expires.isoformat())
        return exc.status < 500                   # a refusal waits for the next day; an outage is tried again soon
    EXPIRY_ACTIONS.labels("delete_opened", env).inc()
    log.info("expiry_delete_opened", cluster_id=cluster_id, namespace=name, request_id=request_id, status=status,
             approval=approval, expires_at=expires.isoformat())
    return True


def _message(ctx: AppContext, cluster_id: str, env: str, name: str, expires: date, day: date) -> tuple[str, str, dict[str, str]]:
    r = ctx.cfg.expiration.rules(env)
    left = (expires - day).days
    subject = f"[cmapi] {name} on {cluster_id} expires on {expires.isoformat()}, in {left} day{'s' if left != 1 else ''}"
    body = (f"The namespace {name} on {cluster_id} ({env}) expires on {expires.isoformat()} (UTC).\n\n"
            f"It keeps running for {r.grace_days} days of grace from that date, and can still be extended. After the grace, "
            "cmapi opens a request to delete it: the request goes through the approval rules, and an operator confirms the "
            "prune before anything is removed from the cluster.\n\n"
            f"To keep it, extend it on the portal's Expiration tab, or with POST /api/v1/clusters/{cluster_id}/namespaces/"
            f"{name}/expiration:extend (at most {r.max_extension_days} days at a time).")
    portal = (ctx.cfg.raw_instance.get("instance") or {}).get("portalUrl")
    return subject, body, ({"Portal": portal} if portal else {})


def _fence(s: Session, lease: Any) -> None:
    if lease:
        s.info["lease"] = lease
        JobRepo(s).fence()


def _lock_namespace(s: Session, cluster_id: str, name: str) -> None:
    """Serialize the actions on one namespace until this transaction ends: a concurrent run waits, then sees this one's row."""
    digest = hashlib.sha256(f"cmapi-expire-check:{cluster_id}/{name}".encode()).digest()
    s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": int.from_bytes(digest[:8], "big", signed=True)})


def _is_recorded(s: Session, cluster_id: str, name: str, expires: date, threshold: int) -> bool:
    return s.scalar(select(ExpirationNoticeRow.id).where(
        ExpirationNoticeRow.cluster_id == cluster_id, ExpirationNoticeRow.namespace == name,
        ExpirationNoticeRow.expires_at == expires.isoformat(), ExpirationNoticeRow.threshold_days == threshold,
        ExpirationNoticeRow.ok.is_(True)).limit(1)) is not None


def _recorded_thresholds(s: Session, cluster_id: str) -> dict[tuple[str, str], set[int]]:
    """(namespace, date) -> the thresholds recorded as done for that date: notices, grace (0) and delete (-1)."""
    out: dict[tuple[str, str], set[int]] = {}
    q = select(ExpirationNoticeRow.namespace, ExpirationNoticeRow.expires_at, ExpirationNoticeRow.threshold_days) \
        .where(ExpirationNoticeRow.cluster_id == cluster_id, ExpirationNoticeRow.ok.is_(True))
    for ns, at, threshold in s.execute(q):
        out.setdefault((ns, at), set()).add(threshold)
    return out


def _last_extensions(s: Session, cluster_id: str, namespace: str | None = None) -> dict[str, datetime]:
    """namespace -> when its last :extend or :set was asked, whatever became of it: a recent try holds the delete a day."""
    q = select(ChangeRequestRow.namespace, func.max(ChangeRequestRow.created_at)) \
        .where(ChangeRequestRow.cluster_id == cluster_id, ChangeRequestRow.reason.in_(EXTENSION_REASONS)) \
        .group_by(ChangeRequestRow.namespace)
    if namespace is not None:
        q = q.where(ChangeRequestRow.namespace == namespace)
    return {ns: at.astimezone(timezone.utc) for ns, at in s.execute(q)}


def _date(raw: Any) -> date | None:
    """`cmapi.net/expires-at`, or None for a value that is not a date: no plan can act on it (GET /expirations logs it)."""
    try:
        return date.fromisoformat(str(raw)) if raw else None
    except ValueError:
        return None
