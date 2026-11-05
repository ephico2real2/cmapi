"""watch_sync: the request is merged. Deliver (apply mode) or wait for Argo CD (argocd mode), then
confirm by a read; a delete stops in awaiting_prune. Re-enqueues itself every poll interval until
synced, or sync_failed after the timeout. prune: an operator confirmed; in apply mode remove the
namespace, then confirm it is gone."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from cmapi.core.clients.kube import ClusterUnreachable, KubeError
from cmapi.core.context import AppContext
from cmapi.core.db.models import JobRow
from cmapi.core.db.repo import JobRepo, RequestRepo
from cmapi.core.errors import Problem
from cmapi.core.git.base import GitUnavailable
from cmapi.core.lifecycle import Event as E, State as S
from cmapi.core.observability import LEAD_TIME, log
from cmapi.core.render.manifests import folder
from cmapi.core.sync import ApplyDelivery, ArgoCdSignal, application_name, confirmed_by_read, not_synced


def _deliverer(ctx: AppContext, cluster_id: str):
    """The write identity for apply delivery: the worker's own ServiceAccount on the hub (the one
    cluster CRC has), or a per-cluster deliverer Secret when one is mounted."""
    from pathlib import Path

    from cmapi.core.clients.kube import KubeClient

    if ctx.deliverer_factory is not None:
        return ctx.deliverer_factory(cluster_id)
    s = ctx.settings
    secret_dir = Path(f"/etc/cmapi/deliverer/{cluster_id}")
    if (secret_dir / "token").exists():
        api_url = (secret_dir / "apiUrl").read_text().strip()
        ca = secret_dir / "ca.crt"
        return KubeClient(cluster_id, api_url, (secret_dir / "token").read_text().strip(),
                          str(ca) if ca.exists() else None)
    if s.kube_token_file.exists():
        return KubeClient(cluster_id, s.kube_api_url, s.kube_token_file.read_text().strip(),
                          str(s.kube_ca_file) if s.kube_ca_file.exists() else None)
    raise RuntimeError(f"no deliverer credential for {cluster_id}")


def _mode(ctx: AppContext, cluster_id: str) -> str:
    st = ctx.registry.get(cluster_id)
    return (st.policy.delivery if st.policy and st.policy.delivery else ctx.delivery.mode)


def _managed(obj: dict | None) -> bool:
    return ((obj or {}).get("metadata", {}).get("labels") or {}).get("cmapi.net/managed") == "true"


def _reader_cache(ctx: AppContext, cluster_id: str):
    """The watch cache; a cluster whose import is not connected is something to wait for, not a job failure."""
    try:
        return ctx.registry.cache(cluster_id)
    except Problem as exc:
        raise _NotYet(exc.detail) from exc


def watch_sync(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status not in (S.MERGED.value, S.SYNC_FAILED.value):
        jobs.done(job)
        return
    # A :retry restarts the clock; the merge time would leave it one attempt.
    retried = (job.payload or {}).get("since")
    since = datetime.fromisoformat(retried) if retried else (row.merged_at or row.updated_at or datetime.now(timezone.utc))
    waited = (datetime.now(timezone.utc) - since).total_seconds()
    files = {p: t for p, t in row.plan["files"].items() if t is not None}
    removed = {p: row.plan["prev"][p] for p, t in row.plan["files"].items() if t is None and p in row.plan.get("prev", {})}
    mode = _mode(ctx, row.cluster_id)
    if row.action == "delete":
        if row.status == S.MERGED.value:
            repo.move(row, E.PRUNE_PENDING, "argocd" if mode == "argocd" else "cmapi-deliverer",
                      "Prune=confirm: waiting for an operator to confirm the prune")
        jobs.done(job)
        if mode == "argocd":
            # The confirmation happens in Argo CD, with no call to cmapi: only a watch of the namespace ends the request.
            jobs.enqueue("prune", request_id=row.request_id, cluster_id=row.cluster_id, delay=ctx.delivery.poll_seconds)
        return
    try:
        if mode == "apply":
            on_main, _ = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
            if on_main != files:
                return _refuse(repo, jobs, row, job, "Git main's folder differs from the approved plan; nothing applied")
            d = ApplyDelivery(_deliverer(ctx, row.cluster_id))
            live = d.client.get_object("Namespace", None, row.namespace)
            if live is not None and not _managed(live):
                # The plan-time check is hours old by now. Server-side apply with force would take it over.
                return _refuse(repo, jobs, row, job, f"{row.namespace} exists on the cluster and cmapi does not manage it; nothing applied")
            jobs.fence()
            n = d.apply_folder(files)
            if removed:
                d.prune_objects(row.namespace, removed)
            repo.event(row, "applied", "cmapi-deliverer", f"server-side applied {n} objects from Git {row.merge_sha[:8] if row.merge_sha else 'main'}")
        else:
            # Three things must hold before a read can confirm: Git main still carries the approved plan (a later
            # change to the folder is a new request, not this one), Argo CD has compared a revision at or after the
            # merge (status.sync.revision is the head of main, so a later merge moves it), and this folder's own objects
            # are Synced (the Application's status covers every namespace, so a neighbour's pending prune says nothing).
            on_main, _ = ctx.git.read_folder(folder(row.cluster_id, row.namespace))
            if on_main != files:
                return _refuse(repo, jobs, row, job, "Git main's folder differs from the approved plan")
            st = ctx.registry.get(row.cluster_id)
            if st.client is None:
                raise ClusterUnreachable(f"{row.cluster_id} is {st.status}")
            app = ArgoCdSignal(st.client, ctx.delivery.argocd_namespace,
                               application_name(ctx.delivery.argocd_root_application, row.cluster_id, row.namespace)).status(row.cluster_id)
            observed = app.revisions or (frozenset({app.revision}) if app.revision else frozenset())
            repo.event(row, "argocd", "argocd", f"{app.sync} {app.health} at {','.join(sorted(r[:8] for r in observed)) or '?'}")
            # A merged request with no merge sha has nothing to compare: it fails closed, not open.
            if not row.merge_sha or not any(ctx.git.contains(r, row.merge_sha) for r in observed):
                raise _NotYet(f"Argo CD compared {sorted(r[:8] for r in observed)}, none holding {(row.merge_sha or 'an unknown merge')[:8]}")
            waiting = not_synced(app, files, row.plan.get("prev") or {})
            if waiting:
                raise _NotYet(f"Argo CD reports {waiting[:3]}")
        cache = _reader_cache(ctx, row.cluster_id)
        ok, why = confirmed_by_read(lambda k, ns, n: cache.get(k, ns, n) or _direct(cache, k, ns, n), row.namespace, files)
        if not ok:
            raise _NotYet(why)
    except (_NotYet, ClusterUnreachable, KubeError, GitUnavailable) as exc:
        if waited > ctx.delivery.sync_timeout_seconds:
            if row.status == S.MERGED.value:
                repo.move(row, E.SYNC_TIMEOUT, "worker", f"not synced after {int(waited)} s: {str(exc)[:160]}")
            jobs.done(job)
            return
        repo.event(row, "sync_wait", "worker", str(exc)[:200])
        jobs.retry(job, str(exc)[:300], ctx.delivery.poll_seconds)
        job.attempts = 0                                  # waiting is not a failure
        return
    repo.move(row, E.SYNCED, "cmapi-deliverer" if mode == "apply" else "argocd", f"confirmed by a read: {why}")
    approval = "auto" if (row.requirement or {}).get("auto") else "human"
    LEAD_TIME.labels(row.plugin, row.action, approval).observe((datetime.now(timezone.utc) - row.created_at).total_seconds())
    jobs.done(job)


def _refuse(repo: RequestRepo, jobs: JobRepo, row, job: JobRow, why: str) -> None:
    """A delivery that must not happen: no retry can make it right, an operator looks at the request."""
    if row.status == S.MERGED.value:
        repo.move(row, E.SYNC_TIMEOUT, "worker", why)
    else:
        repo.event(row, "refused", "worker", why)
    jobs.done(job)


def _direct(cache, kind: str, ns: str | None, name: str):
    try:
        return cache.client.get_object(kind, ns, name)
    except (ClusterUnreachable, KubeError):
        return None


def _prune_wait(repo: RequestRepo, jobs: JobRepo, row, job: JobRow, poll: int, why: str) -> None:
    """Waiting is not a failure: the attempts reset, so the one job this request has is never exhausted. It is not
    silent either: each new reason lands on the request once, and in the log every time."""
    log.warning("prune_waiting", job=job.job_id, request_id=row.request_id, reason=why[:200])
    if job.last_error != why[:2000]:
        repo.event(row, "prune_waiting", "worker", why[:300])
    jobs.retry(job, why, poll)
    job.attempts = 0


def _cannot_read(ctx: AppContext, repo: RequestRepo, jobs: JobRepo, row, job: JobRow, why: str) -> None:
    """A cluster that cannot be read, unreachable or its reader not connected (never connecting included), is a wait
    bounded by time, not by attempts: one clock from the first failed read, running for the design's syncTimeout, the
    bound watch_sync gives the same failure. The registry's relist, up to five minutes away, never decides the outcome.
    Within the bound the reason lands on the request once; past it the request is sync_failed, a legal state that
    keeps the lock and offers :retry (this job again, a new clock) and :revert."""
    now = datetime.now(timezone.utc)
    since = (job.payload or {}).get("unreachable_since")
    if since is None:
        job.payload = {**(job.payload or {}), "unreachable_since": now.isoformat()}
        since = now.isoformat()
    waited = (now - datetime.fromisoformat(since)).total_seconds()
    if waited < ctx.delivery.sync_timeout_seconds:
        _prune_wait(repo, jobs, row, job, ctx.delivery.poll_seconds, why)
        return
    note = f"the cluster could not be read for {int(waited)} s: {why[:160]}"
    if row.status == S.AWAITING_PRUNE.value:
        repo.move(row, E.SYNC_TIMEOUT, "worker", note)
    else:
        repo.event(row, "error", "worker", note)
    jobs.done(job)


def prune(ctx: AppContext, s: Session, job: JobRow) -> None:
    """Ends a delete: only a successful read that finds no namespace confirms it.

    Three outcomes short of that. A cluster that cannot be read (unreachable, or its reader not connected, never
    connecting included) waits for delivery.syncTimeout on one clock from the first failed read, with the reason on
    the request once, then is sync_failed (_cannot_read). A successful read that finds the namespace still there
    (Active, Terminating, whatever) is the operator's wait: unbounded, the reason once, CmapiPruneStuck after a day.
    Everything else, a read refused, a cluster gone from the config, a bug, is a failure: it takes the worker's five
    attempts, and after the last the request is sync_failed, a legal state that keeps the lock and offers :retry (this
    job again) and :revert. A done job on an awaiting_prune request, with nothing left to end it, cannot happen.

    Apply mode deletes only after POST /admin/prune:confirm. A :retry looks again, it confirms nothing."""
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    retrying = row.status == S.SYNC_FAILED.value and row.action == "delete"
    if row.status != S.AWAITING_PRUNE.value and not retrying:
        jobs.done(job)
        return
    mode = _mode(ctx, row.cluster_id)
    try:
        reader = _reader_cache(ctx, row.cluster_id).client
        live = reader.get_object("Namespace", None, row.namespace)
    except (_NotYet, ClusterUnreachable) as exc:
        _cannot_read(ctx, repo, jobs, row, job, f"{type(exc).__name__}: {exc}")
        return
    if (job.payload or {}).get("unreachable_since"):        # a success clears the clock: a later outage starts its own
        job.payload = {k: v for k, v in job.payload.items() if k != "unreachable_since"}
    if live is not None and not _managed(live):
        why = f"{row.namespace} on the cluster is not cmapi-managed; nothing deleted"
        if row.status == S.AWAITING_PRUNE.value:
            repo.move(row, E.SYNC_TIMEOUT, "worker", why)      # :revert restores the folder; waiting cannot fix this
        else:
            repo.event(row, "refused", "worker", why)
        jobs.done(job)
        return
    if mode == "apply" and live is not None and live.get("status", {}).get("phase") != "Terminating":
        if not any(e.event == "prune_confirm" for e in repo.events(row.request_id)):
            _prune_wait(repo, jobs, row, job, ctx.delivery.poll_seconds, "waiting for POST /admin/prune:confirm")
            return
        jobs.fence()
        _deliverer(ctx, row.cluster_id).delete("Namespace", None, row.namespace)
        repo.event(row, "pruned", "cmapi-deliverer", "namespace delete issued")
        try:
            live = reader.get_object("Namespace", None, row.namespace)
        except ClusterUnreachable as exc:
            _cannot_read(ctx, repo, jobs, row, job, f"after the delete, {type(exc).__name__}: {exc}")
            return
    if live is not None:
        # Terminating is not gone: a finalizer can hold it for ever; CmapiPruneStuck says when it has waited too long.
        _prune_wait(repo, jobs, row, job, ctx.delivery.poll_seconds, f"namespace still present ({live.get('status', {}).get('phase', 'Unknown')})")
        return
    event = E.SYNCED if retrying else E.PRUNE_CONFIRMED
    repo.move(row, event, "cmapi-deliverer" if mode == "apply" else "argocd", "absence confirmed by a successful read")
    jobs.done(job)


class _NotYet(RuntimeError):
    pass
