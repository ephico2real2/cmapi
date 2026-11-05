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
from cmapi.core.observability import LEAD_TIME
from cmapi.core.render.manifests import folder
from cmapi.core.sync import ApplyDelivery, ArgoCdSignal, confirmed_by_read


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
            n = d.apply_folder(files)
            if removed:
                d.prune_objects(row.namespace, removed)
            repo.event(row, "applied", "cmapi-deliverer", f"server-side applied {n} objects from Git {row.merge_sha[:8] if row.merge_sha else 'main'}")
        else:
            st = ctx.registry.get(row.cluster_id)
            if st.client is None:
                raise ClusterUnreachable(f"{row.cluster_id} is {st.status}")
            app = ArgoCdSignal(st.client, ctx.delivery.argocd_namespace,
                               ctx.delivery.argocd_root_application.format(clusterId=row.cluster_id)).status(row.cluster_id)
            repo.event(row, "argocd", "argocd", f"{app.sync} {app.health} at {app.revision[:8]}")
            if app.sync != "Synced" or (row.merge_sha and app.revision and not app.revision.startswith(row.merge_sha[:8])
                                        and app.revision != row.merge_sha):
                raise _NotYet(f"Argo CD reports {app.sync} at {app.revision[:8]}")
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


def prune(ctx: AppContext, s: Session, job: JobRow) -> None:
    repo, jobs = RequestRepo(s), JobRepo(s)
    row = repo.get(job.request_id)
    if row.status != S.AWAITING_PRUNE.value:
        jobs.done(job)
        return
    mode = _mode(ctx, row.cluster_id)
    # A strict read. Only a successful read that finds nothing confirms the prune; a read that fails, a reader
    # not yet connected, or a namespace still there (Active, Terminating, anything) is waiting, never a failure:
    # the attempts reset, so an outage cannot exhaust the one job and leave the namespace locked for ever.
    try:
        reader = _reader_cache(ctx, row.cluster_id).client
        live = reader.get_object("Namespace", None, row.namespace)
        if live is not None and not _managed(live):
            repo.event(row, "refused", "worker", f"{row.namespace} on the cluster is not cmapi-managed; nothing deleted")
            jobs.done(job)
            return
        if mode == "apply" and live is not None and live.get("status", {}).get("phase") != "Terminating":
            _deliverer(ctx, row.cluster_id).delete("Namespace", None, row.namespace)
            repo.event(row, "pruned", "cmapi-deliverer", "namespace delete issued")
            live = reader.get_object("Namespace", None, row.namespace)
    except (_NotYet, Problem, ClusterUnreachable, KubeError) as exc:
        jobs.retry(job, str(exc)[:300], ctx.delivery.poll_seconds)
        job.attempts = 0
        return
    if live is not None:
        # Terminating is not gone: a finalizer can hold it for ever; CmapiPruneStuck says when it has waited too long.
        jobs.retry(job, f"namespace still present ({live.get('status', {}).get('phase', 'Unknown')})", ctx.delivery.poll_seconds)
        job.attempts = 0
        return
    repo.move(row, E.PRUNE_CONFIRMED, "cmapi-deliverer" if mode == "apply" else "argocd", "absence confirmed by a successful read")
    jobs.done(job)


class _NotYet(RuntimeError):
    pass
